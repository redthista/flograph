"""AI Assistant settings dialog (Tools > AI Assistant Settings…).

Persists the local-LLM connection (base URL, model, optional API key) via
QSettings, under the same "flograph"/"flograph" org/app used everywhere
else in the UI. load_llm_config() is the read side other UI code calls
before firing an "Ask AI" request.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QHBoxLayout, QLineEdit, QMessageBox, QPushButton,
)

from flograph import ai

_ORG = "flograph"
_APP = "flograph"

_INFO_TEXT = """\
When you click "Ask AI" on a node, three things are sent to the Base URL \
configured here — nothing passes through any flograph-run server first:

1. A fixed instruction describing flograph's node contract (no data — the \
same every time).
2. The current node's source code — the NODE / PARAMS / run() text shown \
in the code editor.
3. The instruction you type (e.g. "format the date column as YYYY-MM-DD").

What is NOT sent:

• The actual data flowing through the node (dataframe or column values) — \
run() is never executed as part of this, so there's no data to send.
• Parameter values set via the Properties panel (file paths, connection \
strings, etc.) — those aren't part of the script text.
• Any other node's code, or the rest of the graph.

One caveat: if a literal value (e.g. a file path or key) is hardcoded \
directly in the node's script instead of set via the Properties panel, it \
will be included — it's part of the source code sent to the server."""


def load_llm_config() -> ai.LLMConfig:
    settings = QSettings(_ORG, _APP)
    return ai.LLMConfig(
        base_url=settings.value("ai/base_url", ai.DEFAULT_BASE_URL, type=str),
        model=settings.value("ai/model", ai.DEFAULT_MODEL, type=str),
        api_key=settings.value("ai/api_key", "", type=str) or None,
        verify_ssl=settings.value("ai/verify_ssl", True, type=bool),
        provider=settings.value("ai/provider", "openai", type=str),
    )


class AiSettingsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AI Assistant Settings")
        self.resize(480, 160)

        config = load_llm_config()

        self._base_url = QLineEdit(config.base_url)
        self._base_url.setPlaceholderText(ai.DEFAULT_BASE_URL)

        # Both formats answer GET /models identically, so fetching models
        # proves nothing about which one the server's chat endpoint speaks.
        self._provider = QComboBox()
        self._provider.addItem(
            "OpenAI-compatible  (/chat/completions)", "openai")
        self._provider.addItem("Anthropic-compatible  (/messages)", "anthropic")
        index = self._provider.findData(config.provider)
        self._provider.setCurrentIndex(max(index, 0))
        self._provider.setToolTip(
            "The wire format the server speaks. Ollama, LM Studio, vLLM, "
            "OpenAI and most corporate gateways are OpenAI-compatible; the "
            "Anthropic API and Anthropic-style proxies are the other.")

        self._model = QComboBox()
        self._model.setEditable(True)
        self._model.setInsertPolicy(QComboBox.NoInsert)
        self._model.addItem(config.model)
        self._model.setCurrentText(config.model)
        self._fetch_models_btn = QPushButton("Fetch Models")
        self._fetch_models_btn.setToolTip(
            "Query the server's /models endpoint, using the Base URL and "
            "API key above")
        self._fetch_models_btn.clicked.connect(self._fetch_models)
        model_row = QHBoxLayout()
        model_row.addWidget(self._model, 1)
        model_row.addWidget(self._fetch_models_btn)

        self._api_key = QLineEdit(config.api_key or "")
        self._api_key.setPlaceholderText("(optional — most local servers don't need one)")
        self._api_key.setEchoMode(QLineEdit.Password)

        self._verify_ssl = QCheckBox("Verify SSL certificates")
        self._verify_ssl.setChecked(config.verify_ssl)
        self._verify_ssl.setToolTip(
            "Uncheck only if the Base URL uses a self-signed or otherwise "
            "untrusted certificate (e.g. behind a corporate proxy). This "
            "makes the connection vulnerable to interception.")

        self._test_btn = QPushButton("Send Test Message")
        self._test_btn.setToolTip(
            "Send one short message to the chat endpoint — the request "
            "\"Ask AI\" actually makes, which fetching models does not test")
        self._test_btn.clicked.connect(self._test_chat)

        form = QFormLayout(self)
        form.addRow("Base URL", self._base_url)
        form.addRow("API format", self._provider)
        form.addRow("Model", model_row)
        form.addRow("API key", self._api_key)
        form.addRow("", self._verify_ssl)
        form.addRow("", self._test_btn)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        self._info_btn = buttons.addButton(
            "What data is sent?", QDialogButtonBox.HelpRole)
        self._info_btn.clicked.connect(self._show_info)
        form.addRow(buttons)

    def _show_info(self) -> None:
        QMessageBox.information(self, "How the AI Assistant Works", _INFO_TEXT)

    def _current_config(self) -> ai.LLMConfig:
        """The settings as typed, not as last saved — so both buttons test
        what the user is about to save."""
        return ai.LLMConfig(
            base_url=self._base_url.text().strip() or ai.DEFAULT_BASE_URL,
            model=self._model.currentText().strip() or ai.DEFAULT_MODEL,
            api_key=self._api_key.text().strip() or None,
            verify_ssl=self._verify_ssl.isChecked(),
            provider=self._provider.currentData(),
        )

    def _test_chat(self) -> None:
        """The one check that exercises what "Ask AI" does: a real
        completion. A server can list models and still refuse to chat."""
        config = self._current_config()
        self._test_btn.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            reply = ai.chat_completion(
                [{"role": "user", "content": "Reply with the word OK."}],
                config)
        except ai.LLMError as exc:
            QMessageBox.warning(self, "Send Test Message", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
            self._test_btn.setEnabled(True)
        QMessageBox.information(
            self, "Send Test Message",
            f"{config.model} answered:\n\n{reply.strip()[:200]}")

    def _fetch_models(self) -> None:
        config = self._current_config()
        self._fetch_models_btn.setEnabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            models = ai.list_models(config)
        except ai.LLMError as exc:
            QMessageBox.warning(self, "Fetch Models", str(exc))
            return
        finally:
            QApplication.restoreOverrideCursor()
            self._fetch_models_btn.setEnabled(True)

        if not models:
            QMessageBox.information(
                self, "Fetch Models", "The server returned no models.")
            return

        current = self._model.currentText()
        self._model.clear()
        self._model.addItems(models)
        self._model.setCurrentText(current if current in models else models[0])

    def _save(self) -> None:
        settings = QSettings(_ORG, _APP)
        settings.setValue("ai/provider", self._provider.currentData())
        settings.setValue(
            "ai/base_url", self._base_url.text().strip() or ai.DEFAULT_BASE_URL)
        settings.setValue(
            "ai/model", self._model.currentText().strip() or ai.DEFAULT_MODEL)
        settings.setValue("ai/api_key", self._api_key.text().strip())
        settings.setValue("ai/verify_ssl", self._verify_ssl.isChecked())
        self.accept()
